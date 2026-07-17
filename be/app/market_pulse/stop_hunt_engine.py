"""
stop_hunt_engine.py
----------------------
Command Center — Stop Loss Hunting: detects whether a liquidity sweep (stop
hunt) is actively occurring — or is likely to soon — on a ticker, and
recommends hunt-resistant stop-loss levels (both price and % from current
price) for a LONG and a SHORT scenario, across Groww India, CoinDCX, US
stocks, and Commodities.

Rather than reinventing sweep detection or S/R strength classification, this
engine orchestrates two already-proven engines in this app:

- smc_liquidity_engine — structural BSL/SSL sweep & grab detection (wick-
  ratio rejection through the prior swing high/low), which gives the exact
  wick-tip "sweep extreme" a professional stop should sit beyond — the
  single most specific invalidation point once a hunt has actually fired.
- price_action.detect_support_resistance + weak_strong_sr_engine's touch-
  count classifier — every nearby S/R level is tagged weak (1-2 touches,
  thin liquidity, a magnet for a future hunt) or strong (3+ touches, genuine
  multi-participant consensus, more likely to actually hold).

On top of those, this engine adds three things professional scalpers use
that aren't already built elsewhere in this codebase:

1. **Round-number proximity** — retail habitually parks stops at clean
   numbers (₹1,000 / $50,000 / 24,000), so a level sitting on or near one is
   an extra-attractive hunt target, independent of its touch count.
2. **Two-tier, ATR-scaled stop-loss recommendation** — Tight/Aggressive
   (closer, better R:R, more hunt risk) and Safe/Hunt-Resistant (wider,
   scaled by how weak the anchoring level is, clears round numbers too),
   for both a LONG and a SHORT scenario, each given in price *and* % from
   current price.
3. **Session-liquidity context** — hunts cluster around session open/close
   and thin-liquidity hours; a lightweight time-of-day flag using this app's
   existing IST/NY session windows.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import pandas as pd

from app.market_pulse.fakeout_4h_engine import (
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    IST_TZ,
    NY_TZ,
    session_mode_for_market,
)
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import _calc_atr, detect_support_resistance
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

_HUNT_STATUS_LABEL = {
    "ACTIVE_SWEEP": "🎣 Active Sweep Detected",
    "HIGH_RISK": "⚠️ High Hunt-Risk Zone",
    "LOW_RISK": "🟢 Low Hunt-Risk",
}

BEST_PRACTICES = [
    "Never rest a stop exactly at the obvious swing high/low — that's precisely where the crowd's "
    "stops already are, which is exactly why price gets pushed there.",
    "Use a volatility-based (ATR) buffer beyond structure, not a flat/round percentage — round % "
    "stops cluster at the same distance everyone else uses.",
    "Anchor stops beyond the wick extreme of a rejection, not the candle body — smart money hunts "
    "the wick, not the close.",
    "Prefer strong (multi-touch) structure as your invalidation point over weak (1-2 touch) "
    "structure — weak levels are the ones most likely to be swept before any real move starts.",
    "Nudge a stop away from a nearby round number even if the structure math lands you close to "
    "one — round numbers attract extra resting orders on their own.",
    "Widen stops (and correspondingly reduce position size) around session opens/closes, low-"
    "liquidity hours, and index-expiry days — hunts cluster in thin liquidity.",
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


def _is_near_round_number(level: float, atr: float) -> tuple[bool, float | None]:
    """Flag a price level sitting suspiciously close to a 'clean' round number."""
    if level is None or level <= 0 or atr <= 0:
        return False, None
    magnitude = 10 ** math.floor(math.log10(level))
    candidates: set[float] = set()
    for step_mult in (1, 2, 5):
        for scale in (magnitude / 10, magnitude):
            step = step_mult * scale
            if step <= 0:
                continue
            candidates.add(round(level / step) * step)
    if not candidates:
        return False, None
    best = min(candidates, key=lambda c: abs(c - level))
    dist = abs(best - level)
    is_near = 0 < best and dist <= atr * 0.5
    return is_near, (best if is_near else None)


def _session_risk_note(market: str) -> str | None:
    """Lightweight time-of-day liquidity-risk flag using this app's existing
    IST/NY session-window constants — hunts cluster around opens/closes and
    thin-liquidity windows."""
    mode = session_mode_for_market(market)
    if mode == "india":
        now = datetime.now(IST_TZ).time()
        open_minutes = abs((now.hour * 60 + now.minute) - (INDIA_MARKET_OPEN.hour * 60 + INDIA_MARKET_OPEN.minute))
        close_minutes = abs((now.hour * 60 + now.minute) - (INDIA_MARKET_CLOSE.hour * 60 + INDIA_MARKET_CLOSE.minute))
        if open_minutes <= 20:
            return "🕐 Within 20 min of NSE open — the first 15-30 min routinely sees stop hunts through the overnight/gap range before a genuine direction sets in."
        if close_minutes <= 20:
            return "🕐 Within 20 min of NSE close — expiry-day and closing-auction flows often sweep intraday levels late in the session."
        return None
    # Crypto/US: flag thin-liquidity windows (Asian session for crypto majors, US pre/after-hours).
    now_ny = datetime.now(NY_TZ)
    if now_ny.weekday() >= 5:
        return "🕐 Weekend — crypto liquidity is thinner than weekday sessions, exaggerating sweep moves."
    hour = now_ny.hour
    if hour < 4 or hour >= 20:
        return "🕐 Outside the US day session (pre-market/after-hours or Asian-session hours) — thinner liquidity makes sweeps larger and faster."
    return None


def _stop_tier(anchor: float, atr: float, buffer_mult: float, direction: str, price: float) -> dict[str, Any]:
    if direction == "LONG":
        stop = anchor - atr * buffer_mult
        stop = min(stop, price - atr * 0.1)
    else:
        stop = anchor + atr * buffer_mult
        stop = max(stop, price + atr * 0.1)

    near_round, round_level = _is_near_round_number(stop, atr)
    if near_round:
        stop = stop - atr * 0.25 if direction == "LONG" else stop + atr * 0.25

    pct = abs(price - stop) / price * 100 if price else 0.0
    return {
        "price": round(float(stop), 6),
        "pct": round(pct, 2),
        "nudged_for_round_number": bool(near_round),
        "round_number_avoided": round(round_level, 4) if near_round and round_level else None,
    }


def _anchor_for_direction(
    direction: str, price: float, atr: float, live: dict, sr_side: dict | None,
) -> dict[str, Any]:
    """Pick the best available invalidation anchor for a stop, in priority order:
    a fresh sweep's wick extreme > the nearest S/R level (tagged weak/strong) >
    the SMC engine's structural BSL/SSL > an ATR-only fallback. A candidate is only
    used if it's within a sane distance of price (≤8×ATR) — a technically-nearest
    S/R level that's actually far away (e.g. only resistance left after a strong
    uptrend) makes a useless, wildly wide "stop" if used as-is."""
    max_dist = atr * 8.0
    sweep_ext = live.get("sweep_extreme")
    live_dir = live.get("direction")
    event_type = live.get("event_type")

    if sweep_ext is not None and live_dir == direction and event_type in ("SWEEP", "GRAB"):
        if abs(float(sweep_ext) - price) <= max_dist:
            return {"source": "sweep_extreme", "level": float(sweep_ext), "strength": "very_strong",
                    "label": f"the {event_type.lower()}'s wick extreme"}

    candidates: list[dict[str, Any]] = []
    if sr_side is not None and abs(float(sr_side["price"]) - price) <= max_dist:
        strength = sr_side.get("strength", "moderate")
        candidates.append({
            "source": "sr_level", "level": float(sr_side["price"]), "strength": strength,
            "label": f"the nearby {strength} S/R level ({sr_side.get('touches', 1)} touch(es))",
            "dist": abs(float(sr_side["price"]) - price),
        })

    structural = live.get("ssl_level") if direction == "LONG" else live.get("bsl_level")
    if structural is not None and abs(float(structural) - price) <= max_dist:
        candidates.append({
            "source": "structural", "level": float(structural), "strength": "moderate",
            "label": "the nearest structural swing level",
            "dist": abs(float(structural) - price),
        })

    if candidates:
        best = min(candidates, key=lambda c: c["dist"])
        best.pop("dist")
        return best

    fallback = price - atr * 2.0 if direction == "LONG" else price + atr * 2.0
    return {"source": "atr_fallback", "level": fallback, "strength": "weak",
            "label": "a pure ATR-based fallback (no nearby structure found)"}


_BUFFER_BY_STRENGTH = {
    "very_strong": (0.15, 0.40),   # (tight, safe) ATR multiples
    "strong": (0.25, 0.60),
    "moderate": (0.35, 0.85),
    "weak": (0.50, 1.10),
}


def _recommend_stops(direction: str, price: float, atr: float, live: dict, sr_side: dict | None) -> dict[str, Any]:
    anchor = _anchor_for_direction(direction, price, atr, live, sr_side)
    tight_mult, safe_mult = _BUFFER_BY_STRENGTH.get(anchor["strength"], (0.35, 0.85))
    tight = _stop_tier(anchor["level"], atr, tight_mult, direction, price)
    safe = _stop_tier(anchor["level"], atr, safe_mult, direction, price)
    return {
        "direction": direction,
        "anchor": anchor,
        "tight": tight,
        "safe": safe,
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

    # 1. Liquidity sweep / grab / run detection (smc_liquidity_engine).
    liq_cfg = LiquidityConfig(execution_tf=timeframe, use_mtf=False, strategy_mode="Sweep / Grab")
    work, events, bull_fvgs, bear_fvgs = implement_liquidity_strategy(df, liq_cfg)
    live = evaluate_live_signal(work, events, liq_cfg, bull_fvgs=bull_fvgs, bear_fvgs=bear_fvgs, reference_price=price)

    # 2. Nearby S/R, tagged weak/strong by touch count.
    sr = detect_support_resistance(normalize_ohlcv(df), window=5, num_levels=3)
    supports = list(sr.get("supports") or [])
    resistances = list(sr.get("resistances") or [])
    all_touches = [int(x.get("touches", 1)) for x in supports + resistances] or [1]
    median_touches = sorted(all_touches)[len(all_touches) // 2]
    for lvl in supports + resistances:
        lvl["strength"] = _classify_strength(int(lvl.get("touches", 1)), median_touches)
    nearest_support = supports[0] if supports else None
    nearest_resistance = resistances[0] if resistances else None

    # 3. Round-number check on the two nearest levels.
    round_flags: list[str] = []
    for lvl, tag in ((nearest_support, "support"), (nearest_resistance, "resistance")):
        if lvl is None:
            continue
        is_near, clean = _is_near_round_number(float(lvl["price"]), atr)
        if is_near:
            round_flags.append(
                f"Nearest {tag} ({lvl['price']:,.4g}) sits right next to the round number {clean:,.4g} — "
                "extra stop-cluster risk beyond just the structure itself."
            )

    # 4. Overall hunt status.
    event_type = live.get("event_type")
    phase = live.get("phase")
    active_sweep = event_type in ("SWEEP", "GRAB") and phase in ("SWEEP_DETECTED", "LIQUIDITY_ENTRY")
    weak_nearby = (nearest_support and nearest_support["strength"] == "weak") or \
                  (nearest_resistance and nearest_resistance["strength"] == "weak")

    if active_sweep:
        hunt_status = "ACTIVE_SWEEP"
    elif weak_nearby:
        hunt_status = "HIGH_RISK"
    else:
        hunt_status = "LOW_RISK"

    # 5. Stop-loss recommendations for both scenarios.
    long_stops = _recommend_stops("LONG", price, atr, live, nearest_support)
    short_stops = _recommend_stops("SHORT", price, atr, live, nearest_resistance)

    # 6. Reasoning.
    reasons: list[str] = []
    if active_sweep:
        side = "buy-side (above)" if live.get("direction") == "SHORT" else "sell-side (below)"
        reasons.append(
            f"🎣 A liquidity {event_type.lower()} just fired {side} — price wicked through the prior "
            f"structural level and closed back inside range, the classic 'hunt-and-reverse' signature. "
            f"Fade toward the opposite liquidity pool is the textbook read here."
        )
        for r in (live.get("reasons") or [])[:2]:
            reasons.append(f"· {r}")
    elif weak_nearby:
        reasons.append(
            "⚠️ No sweep has fired yet, but a weak (thinly-tested) level sits nearby — thin liquidity "
            "like this is exactly what attracts a hunt before the real move."
        )
    else:
        reasons.append(
            "🟢 No active sweep and the nearby structure is reasonably strong (multiple touches) — "
            "lower (not zero) hunt risk right now."
        )

    if nearest_support:
        reasons.append(
            f"Nearest support {nearest_support['price']:,.4g} — {nearest_support['strength']} "
            f"({nearest_support.get('touches', 1)} touch(es))."
        )
    if nearest_resistance:
        reasons.append(
            f"Nearest resistance {nearest_resistance['price']:,.4g} — {nearest_resistance['strength']} "
            f"({nearest_resistance.get('touches', 1)} touch(es))."
        )
    reasons.extend(round_flags)

    session_note = _session_risk_note(market)
    if session_note:
        reasons.append(session_note)

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "price": price, "atr": round(float(atr), 6),
        "hunt_status": hunt_status,
        "event_type": event_type,
        "sweep_extreme": live.get("sweep_extreme"),
        "bsl_level": live.get("bsl_level"),
        "ssl_level": live.get("ssl_level"),
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "long_stops": long_stops,
        "short_stops": short_stops,
        "reasons": reasons,
        "session_note": session_note,
    }


def analyze_ticker_multi_tf(
    ticker: str, timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    per_tf: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        try:
            per_tf[tf] = analyze_ticker(ticker, tf, market, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Stop-hunt analysis failed for %s %s: %s", ticker, tf, exc)
            per_tf[tf] = {"ticker": ticker, "market": market, "timeframe": tf, "error": str(exc)[:200]}
    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_tickers_multi_tf(
    tickers: list[str], timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    return [
        analyze_ticker_multi_tf(ticker, timeframes, market, groww_token=groww_token, exchange=exchange)
        for ticker in tickers
    ]
