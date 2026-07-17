"""
take_profit_engine.py
----------------------
Command Center — Take Profit Targets: for a LONG and a SHORT scenario on any
ticker/timeframe, combines several independent, professional target-setting
methodologies into two tiers — TP1 (Conservative/High-Probability) and TP2
(Extended/Momentum) — each given in price *and* % from current price, across
Groww India, CoinDCX, US stocks, and Commodities.

Rather than inventing a single new indicator, this engine orchestrates four
already-proven, structurally-independent reads already in this app:

- price_action.detect_support_resistance + weak_strong_sr_engine's touch-count
  classifier — the nearest *strong* (multi-touch) level in the profit
  direction is the highest-probability zone to book profit, professionally
  pulled back slightly ahead of the exact level rather than resting the order
  on it (limit orders cluster right at obvious levels; price often reverses
  just short of them).
- price_action.detect_chart_patterns + pattern_breakout_tab's extended
  detectors (flags/cup-and-handle/triple top-bottom) — every detected
  pattern already carries an objective, structure-derived measured-move
  "target".
- price_action.analyze_fibonacci — 127.2% / 161.8% / 261.8% extensions of the
  most recent swing, the standard technique for projecting a target when
  price is breaking into new territory with no nearby structure.
- smc_liquidity_engine — the opposite-side structural liquidity pool (BSL for
  a LONG, SSL for a SHORT). In Smart Money Concepts terms this is "draw on
  liquidity": price statistically gravitates toward the nearest un-swept pool
  of resting opposing orders before it reverses, making that pool a genuine,
  independently-derived target rather than a guess.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pattern_breakout_tab import detect_extended_chart_patterns
from app.market_pulse.price_action import (
    _calc_atr,
    analyze_fibonacci,
    detect_chart_patterns,
    detect_support_resistance,
)
from app.market_pulse.stop_hunt_engine import _is_near_round_number
from app.market_pulse.weak_strong_sr_engine import _classify_strength
from app.trading_hubs.smc_liquidity_engine import (
    LiquidityConfig,
    evaluate_live_signal,
    implement_liquidity_strategy,
)

logger = logging.getLogger(__name__)

__all__ = ["analyze_ticker", "analyze_ticker_multi_tf", "analyze_tickers_multi_tf"]

_LOOKBACK_BARS = 400
_MIN_BARS = 60

_TP_STATUS_LABEL = {
    "HIGH_CONFLUENCE": "🎯 High-Confluence Target",
    "MODERATE_CONFLUENCE": "📍 Moderate-Confluence Target",
    "LOW_CONFLUENCE": "🌫️ Low-Confluence — Thin Structure",
}

BEST_PRACTICES = [
    "Book profit slightly ahead of an obvious level, not exactly on it — resting limit orders "
    "cluster right at the round/structural price, and price often reverses just short of filling them.",
    "Prefer a level with genuine confluence (S/R + pattern target + liquidity draw all pointing to a "
    "similar zone) over any single method in isolation — agreement across independent reads is what "
    "makes a target trustworthy, not one indicator's precision.",
    "Scale out in tiers (TP1 partial, move stop to breakeven, let a runner ride to TP2) rather than an "
    "all-or-nothing exit — this locks in an edge even when the extended target never gets tagged.",
    "Treat a round-number target as a *feature*, not a coincidence — resting opposing orders cluster "
    "there, which is exactly what makes it a plausible reaction zone.",
    "An extended (TP2) target is a probability tilt, not a promise — the farther a target sits from "
    "current price, the more it depends on a genuine trend/momentum continuation to ever be reached.",
    "Re-anchor targets to fresh structure after each new swing high/low — a target computed on stale "
    "structure becomes progressively less reliable as price moves away from the data it was built on.",
]


def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=_LOOKBACK_BARS)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=_LOOKBACK_BARS, market=market),
        )
    return df


def _target_tier(
    anchor: float, atr: float, pullback_mult: float, direction: str, price: float,
) -> dict[str, Any]:
    """Book profit `pullback_mult` ATRs ahead of the anchor level, not on it."""
    if direction == "LONG":
        target = anchor - atr * pullback_mult
        target = max(target, price + atr * 0.2)
    else:
        target = anchor + atr * pullback_mult
        target = min(target, price - atr * 0.2)

    near_round, round_level = _is_near_round_number(target, atr)
    pct = abs(target - price) / price * 100 if price else 0.0
    return {
        "price": round(float(target), 6),
        "pct": round(pct, 2),
        "near_round_number": bool(near_round),
        "round_number": round(round_level, 4) if near_round and round_level else None,
    }


def _pattern_target(patterns: list[dict], direction: str, price: float) -> dict[str, Any] | None:
    want_bias = "BULLISH" if direction == "LONG" else "BEARISH"
    candidates = [
        p for p in patterns
        if p.get("bias") == want_bias and p.get("target") is not None
        and ((float(p["target"]) > price) if direction == "LONG" else (float(p["target"]) < price))
    ]
    if not candidates:
        return None
    rank = {"VERY HIGH": 3, "HIGH": 2, "MODERATE": 1}
    best = max(candidates, key=lambda p: (rank.get(p.get("reliability"), 0), -abs(float(p["target"]) - price)))
    return {"level": float(best["target"]), "name": best.get("name", "pattern"), "reliability": best.get("reliability", "MODERATE")}


def _fib_extension_target(fib: dict, direction: str, price: float) -> dict[str, Any] | None:
    exts = fib.get("extensions") or {}
    candidates = []
    for name, level in exts.items():
        level = float(level)
        if direction == "LONG" and level > price:
            candidates.append((name, level))
        elif direction == "SHORT" and level < price:
            candidates.append((name, level))
    if not candidates:
        return None
    # Nearest extension first — the most conservative of the extension levels.
    name, level = min(candidates, key=lambda c: abs(c[1] - price))
    return {"level": level, "name": name}


def _tp1_anchor(
    direction: str, price: float, atr: float, sr_side: dict | None, pattern: dict | None,
) -> dict[str, Any]:
    """Nearest credible, high-probability target: strong/moderate S/R first,
    then a pattern's own measured-move target, then a pure ATR fallback."""
    max_dist = atr * 10.0
    candidates: list[dict[str, Any]] = []
    if sr_side is not None and abs(float(sr_side["price"]) - price) <= max_dist:
        strength = sr_side.get("strength", "moderate")
        candidates.append({
            "source": "sr_level", "level": float(sr_side["price"]),
            "label": f"the nearby {strength} S/R level ({sr_side.get('touches', 1)} touch(es))",
            "confluent": strength in ("strong", "very_strong"),
            "dist": abs(float(sr_side["price"]) - price),
        })
    if pattern is not None and abs(pattern["level"] - price) <= max_dist:
        candidates.append({
            "source": "pattern", "level": pattern["level"],
            "label": f"the {pattern['name']} measured-move target ({pattern['reliability']} reliability)",
            "confluent": pattern["reliability"] in ("HIGH", "VERY HIGH"),
            "dist": abs(pattern["level"] - price),
        })
    if candidates:
        best = min(candidates, key=lambda c: c["dist"])
        best.pop("dist")
        best["n_methods"] = len(candidates)
        return best

    fallback = price + atr * 2.5 if direction == "LONG" else price - atr * 2.5
    return {"source": "atr_fallback", "level": fallback, "label": "a pure ATR-based fallback (no nearby structure found)",
            "confluent": False, "n_methods": 0}


def _tp2_anchor(
    direction: str, price: float, atr: float, tp1_level: float, live: dict,
    fib_target: dict | None, pattern: dict | None,
) -> dict[str, Any]:
    """Farthest reasonable extended target: the SMC opposite-side liquidity
    draw, a Fibonacci extension, or a farther pattern target — capped at a
    sane distance so a technically-valid-but-absurdly-far level never gets
    recommended as-is."""
    max_dist = atr * 18.0
    tp1_dist = abs(tp1_level - price)
    candidates: list[dict[str, Any]] = []

    def _farther_than_tp1(level: float) -> bool:
        # TP2 is the extended/momentum tier — it must sit farther out than TP1,
        # otherwise the "conservative vs extended" tiering makes no sense.
        return abs(level - price) > tp1_dist

    structural = live.get("bsl_level") if direction == "LONG" else live.get("ssl_level")
    if structural is not None:
        lvl = float(structural)
        on_side = (lvl > price) if direction == "LONG" else (lvl < price)
        if on_side and abs(lvl - price) <= max_dist and _farther_than_tp1(lvl):
            candidates.append({
                "source": "liquidity_draw", "level": lvl,
                "label": "the opposite-side structural liquidity pool (SMC 'draw on liquidity')",
                "dist": abs(lvl - price),
            })

    if fib_target is not None and abs(fib_target["level"] - price) <= max_dist and _farther_than_tp1(fib_target["level"]):
        candidates.append({
            "source": "fib_extension", "level": fib_target["level"],
            "label": f"the {fib_target['name']} Fibonacci extension of the recent swing",
            "dist": abs(fib_target["level"] - price),
        })

    if pattern is not None and abs(pattern["level"] - price) <= max_dist and _farther_than_tp1(pattern["level"]):
        candidates.append({
            "source": "pattern", "level": pattern["level"],
            "label": f"the {pattern['name']} measured-move target ({pattern['reliability']} reliability)",
            "dist": abs(pattern["level"] - price),
        })

    if candidates:
        best = max(candidates, key=lambda c: c["dist"])
        best.pop("dist")
        return best

    # Golden-ratio extension of TP1's own distance — a legitimate, self-consistent
    # fallback when no independent extended target is available.
    tp1_dist = abs(tp1_level - price)
    fallback = price + tp1_dist * 1.618 if direction == "LONG" else price - tp1_dist * 1.618
    return {"source": "golden_extension", "level": fallback,
            "label": "a 1.618x golden-ratio extension of the TP1 distance (no independent extended target found)"}


def _recommend_targets(
    direction: str, price: float, atr: float, live: dict, sr_side: dict | None,
    patterns: list[dict], fib: dict,
) -> dict[str, Any]:
    pattern = _pattern_target(patterns, direction, price)
    fib_target = _fib_extension_target(fib, direction, price)

    tp1_anchor = _tp1_anchor(direction, price, atr, sr_side, pattern)
    tp1 = _target_tier(tp1_anchor["level"], atr, 0.20, direction, price)

    tp2_anchor = _tp2_anchor(direction, price, atr, tp1_anchor["level"], live, fib_target, pattern)
    tp2 = _target_tier(tp2_anchor["level"], atr, 0.0, direction, price)

    return {
        "direction": direction,
        "tp1_anchor": tp1_anchor,
        "tp1": tp1,
        "tp2_anchor": tp2_anchor,
        "tp2": tp2,
        "confluent": bool(tp1_anchor.get("confluent")),
        "n_methods": int(tp1_anchor.get("n_methods", 0)),
    }


def analyze_ticker(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": f"Insufficient {timeframe} data ({len(df)} bars, need {_MIN_BARS}+).",
        }

    price = float(df["close"].iloc[-1])
    atr = _calc_atr(df, 14)
    if not atr or atr <= 0:
        atr = max(price * 0.005, 1e-6)

    df_norm = normalize_ohlcv(df)

    # 1. Nearby S/R, tagged weak/strong by touch count.
    sr = detect_support_resistance(df_norm, window=5, num_levels=3)
    supports = list(sr.get("supports") or [])
    resistances = list(sr.get("resistances") or [])
    all_touches = [int(x.get("touches", 1)) for x in supports + resistances] or [1]
    median_touches = sorted(all_touches)[len(all_touches) // 2]
    for lvl in supports + resistances:
        lvl["strength"] = _classify_strength(int(lvl.get("touches", 1)), median_touches)
    nearest_support = supports[0] if supports else None
    nearest_resistance = resistances[0] if resistances else None

    # 2. Chart-pattern measured-move targets (base + extended flag/cup/triple detectors).
    patterns = detect_chart_patterns(df_norm) + detect_extended_chart_patterns(df_norm)

    # 3. Fibonacci extensions off the most recent swing.
    fib = analyze_fibonacci(df_norm, lookback=100)

    # 4. SMC structural liquidity pools (opposite-side "draw on liquidity").
    liq_cfg = LiquidityConfig(execution_tf=timeframe, use_mtf=False, strategy_mode="Sweep / Grab")
    work, events, bull_fvgs, bear_fvgs = implement_liquidity_strategy(df, liq_cfg)
    live = evaluate_live_signal(work, events, liq_cfg, bull_fvgs=bull_fvgs, bear_fvgs=bear_fvgs, reference_price=price)

    # 5. Two-tier targets for both scenarios.
    long_targets = _recommend_targets("LONG", price, atr, live, nearest_resistance, patterns, fib)
    short_targets = _recommend_targets("SHORT", price, atr, live, nearest_support, patterns, fib)

    # 6. Overall confluence status (best of the two directions).
    best_methods = max(long_targets["n_methods"], short_targets["n_methods"])
    if long_targets["confluent"] or short_targets["confluent"]:
        tp_status = "HIGH_CONFLUENCE"
    elif best_methods >= 1:
        tp_status = "MODERATE_CONFLUENCE"
    else:
        tp_status = "LOW_CONFLUENCE"

    # 7. Reasoning.
    reasons: list[str] = []
    if tp_status == "HIGH_CONFLUENCE":
        reasons.append(
            "🎯 Multiple independent methods (S/R strength, pattern measured-move, liquidity draw) "
            "point to a similar zone — a genuinely higher-probability target, not a single indicator's guess."
        )
    elif tp_status == "MODERATE_CONFLUENCE":
        reasons.append(
            "📍 One credible structural or pattern-based target found — usable, but without independent "
            "confirmation from a second method."
        )
    else:
        reasons.append(
            "🌫️ No nearby structure, pattern target, or liquidity pool found within a sane distance — "
            "targets below fall back to a pure ATR/Fibonacci projection and carry lower confidence."
        )

    if nearest_resistance:
        reasons.append(
            f"Nearest resistance {nearest_resistance['price']:,.4g} — {nearest_resistance['strength']} "
            f"({nearest_resistance.get('touches', 1)} touch(es))."
        )
    if nearest_support:
        reasons.append(
            f"Nearest support {nearest_support['price']:,.4g} — {nearest_support['strength']} "
            f"({nearest_support.get('touches', 1)} touch(es))."
        )
    if patterns:
        bull_p = [p for p in patterns if p.get("bias") == "BULLISH"]
        bear_p = [p for p in patterns if p.get("bias") == "BEARISH"]
        if bull_p:
            reasons.append("Bullish pattern target(s): " + "; ".join(f"{p['name']} → {p.get('target', 0):,.4g}" for p in bull_p[:2]))
        if bear_p:
            reasons.append("Bearish pattern target(s): " + "; ".join(f"{p['name']} → {p.get('target', 0):,.4g}" for p in bear_p[:2]))

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "price": price, "atr": round(float(atr), 6),
        "tp_status": tp_status,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "long_targets": long_targets,
        "short_targets": short_targets,
        "reasons": reasons,
    }


def analyze_ticker_multi_tf(
    ticker: str, timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    per_tf: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        try:
            per_tf[tf] = analyze_ticker(ticker, tf, market, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Take-profit analysis failed for %s %s: %s", ticker, tf, exc)
            per_tf[tf] = {"ticker": ticker, "market": market, "timeframe": tf, "error": str(exc)[:200]}
    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_tickers_multi_tf(
    tickers: list[str], timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    return [
        analyze_ticker_multi_tf(ticker, timeframes, market, groww_token=groww_token, exchange=exchange)
        for ticker in tickers
    ]
