"""
smc_five_filter_engine.py
--------------------------
5 SMC Filter — the 5 checks that separate an A+ Smart Money trade from a
weak one, plus 3 entry execution models.
https://www.youtube.com/watch?v=uzeLz80FVVY&t=54s

The 5 filters (ALL must pass before a setup is considered A+):
1. Permission     — price must originate from an UNMITIGATED higher-timeframe
                     supply/demand zone. A bullish (demand) zone permits buys
                     only; a bearish (supply) zone permits sells only.
2. Footprint       — the zone's origin must be the footprint of smart money:
                     a liquidity sweep of a prior swing high/low, followed by
                     a sharp displacement that breaks market structure.
3. Inefficiency    — an unfilled Fair Value Gap (imbalance) must exist in the
                     same leg, in the same direction as the zone.
4. Location        — the zone must sit in the discount half of the leg for a
                     bullish (buy) setup, or the premium half for a bearish
                     (sell) setup. Mid-range setups are rejected outright.
5. Exit Test       — there must be untouched higher-timeframe liquidity
                     (an opposing swing) ahead of price, far enough away to
                     clear a minimum reward:risk. No room to target = no trade.

Once all 5 pass, one of 3 entry models executes:
- Aggressive        — enter the moment price is inside the zone (limit-style,
                       at the zone midpoint), stop beyond the zone. Rarely
                       misses a trade, but no reversal confirmation.
- Conservative       — wait for price to tap the zone AND a lower-timeframe
                       Change of Character (ChoCh) to confirm the reversal
                       before entering. Tighter stop, better R:R, can miss
                       fast moves.
- Ultra-Conservative — stacks a second confirmation on top of Conservative:
                       after the LTF ChoCh, also wait for a same-direction LTF
                       Fair Value Gap (continuation) before entering. The
                       closest single-extra-timeframe proxy for the video's
                       "confirm on 1h, then 15m, then 1m" cascade — exceptional
                       R:R and precision, but the most frequently-missed
                       entries of the three.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_FIVE_FILTER_URL = "https://www.youtube.com/watch?v=uzeLz80FVVY&t=54s"

LTF_OPTIONS = ["1m", "5m", "15m", "30m", "1h"]
HTF_OPTIONS = ["1h", "4h", "1d"]
ENTRY_MODEL_OPTIONS = ["Aggressive", "Conservative", "Ultra-Conservative"]

PHASE_NONE = "NO_SETUP"
PHASE_CONFIRMED = "A_PLUS_CONFIRMED"
PHASE_ENTRY = "FILTER_ENTRY"

FILTER_NAMES = ["Permission", "Footprint", "Inefficiency", "Location", "Exit Test"]


@dataclass
class FiveFilterConfig:
    ltf: str = "15m"
    htf: str = "4h"
    swing_window: int = 5
    zone_lookback_bars: int = 60
    displacement_atr_mult: float = 1.3
    leg_lookback_bars: int = 80
    min_rr_ratio: float = 1.5
    rr_ratio_fallback: float = 2.0
    entry_model: str = "Conservative"
    max_setup_age_bars: int = 30
    take_confidence_threshold: float = 60.0
    min_bars: int = 80
    lookback_bars: int = 500


# ---------------------------------------------------------------------------
# Shared low-level helpers (self-contained — mirrors the style used across
# the other smc_* engines rather than importing another engine's internals)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def _swing_columns(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df.copy()
    half = max(1, window // 2)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    swing_hi = np.full(n, np.nan)
    swing_lo = np.full(n, np.nan)

    for i in range(half, n - half):
        w_hi = highs[i - half : i + half + 1].max()
        w_lo = lows[i - half : i + half + 1].min()
        if highs[i] == w_hi:
            swing_hi[i] = highs[i]
        if lows[i] == w_lo:
            swing_lo[i] = lows[i]

    out["swing_high"] = swing_hi
    out["swing_low"] = swing_lo
    return out


# ---------------------------------------------------------------------------
# Filter 1 — Permission: latest UNMITIGATED HTF supply/demand zone
# ---------------------------------------------------------------------------

def find_unmitigated_zone(df_htf: pd.DataFrame, cfg: FiveFilterConfig) -> dict[str, Any] | None:
    """Origin (opposite-colour) candle of the most recent strong-displacement
    impulse that has NOT since been traded back through."""
    atr = _atr(df_htf, 14)
    ranges = df_htf["high"] - df_htf["low"]
    opens, closes = df_htf["open"].values, df_htf["close"].values
    n = len(df_htf)
    start = max(1, n - cfg.zone_lookback_bars)

    for i in range(n - 1, start - 1, -1):
        if pd.isna(atr.iloc[i]) or ranges.iloc[i] <= atr.iloc[i] * cfg.displacement_atr_mult:
            continue
        impulse_bullish = closes[i] > opens[i]
        prev = i - 1
        prev_bullish = closes[prev] > opens[prev]
        if impulse_bullish == prev_bullish:
            continue

        zone = {
            "bullish": impulse_bullish,
            "top": float(df_htf["high"].iloc[prev]),
            "bottom": float(df_htf["low"].iloc[prev]),
            "index": prev,
            "impulse_index": i,
            "timestamp": df_htf.index[prev],
        }
        after = df_htf.iloc[i + 1 :]
        touched = bool(((after["low"] <= zone["top"]) & (after["high"] >= zone["bottom"])).any()) if not after.empty else False
        if touched:
            continue  # mitigated — permission revoked, keep looking further back
        return zone

    return None


# ---------------------------------------------------------------------------
# Filter 2 — Footprint: liquidity sweep of a prior swing right before the zone
# ---------------------------------------------------------------------------

def sweep_before_zone(df_htf: pd.DataFrame, zone: dict[str, Any], cfg: FiveFilterConfig) -> dict[str, Any] | None:
    swung = _swing_columns(df_htf, cfg.swing_window)
    half = max(1, cfg.swing_window // 2)
    zi = zone["index"]
    lookback_start = max(0, zi - cfg.zone_lookback_bars)

    if zone["bullish"]:
        window_lo = swung["swing_low"].values[lookback_start : max(lookback_start + 1, zi - half)]
        valid = window_lo[~np.isnan(window_lo)]
        if not valid.size:
            return None
        level = float(valid[-1])
        span = df_htf.iloc[max(0, zi - 3) : zi + 1]
        swept = bool((span["low"] < level).any() and float(df_htf["close"].iloc[zi]) > level)
        if not swept:
            return None
        return {"direction": "sell_side", "level": level}

    window_hi = swung["swing_high"].values[lookback_start : max(lookback_start + 1, zi - half)]
    valid = window_hi[~np.isnan(window_hi)]
    if not valid.size:
        return None
    level = float(valid[-1])
    span = df_htf.iloc[max(0, zi - 3) : zi + 1]
    swept = bool((span["high"] > level).any() and float(df_htf["close"].iloc[zi]) < level)
    if not swept:
        return None
    return {"direction": "buy_side", "level": level}


# ---------------------------------------------------------------------------
# Filter 3 — Inefficiency: unfilled FVG in the same leg/direction as the zone
# ---------------------------------------------------------------------------

def fvg_in_zone_leg(df_htf: pd.DataFrame, zone: dict[str, Any]) -> dict[str, Any] | None:
    zi, ii = zone["index"], zone["impulse_index"]
    end = min(len(df_htf), ii + 3)
    for k in range(max(zi + 2, ii), end):
        if k >= len(df_htf) or k < 2:
            continue
        if zone["bullish"] and df_htf["low"].iloc[k] > df_htf["high"].iloc[k - 2]:
            top, bottom = float(df_htf["low"].iloc[k]), float(df_htf["high"].iloc[k - 2])
            filled = bool((df_htf["low"].iloc[k + 1 :] <= bottom).any())
            return {"top": top, "bottom": bottom, "filled": filled}
        if not zone["bullish"] and df_htf["high"].iloc[k] < df_htf["low"].iloc[k - 2]:
            top, bottom = float(df_htf["low"].iloc[k - 2]), float(df_htf["high"].iloc[k])
            filled = bool((df_htf["high"].iloc[k + 1 :] >= top).any())
            return {"top": top, "bottom": bottom, "filled": filled}
    return None


# ---------------------------------------------------------------------------
# Filter 4 — Location: discount (buys) / premium (sells) of the broader leg
# ---------------------------------------------------------------------------

def leg_discount_premium(df_htf: pd.DataFrame, zone: dict[str, Any], cfg: FiveFilterConfig) -> dict[str, Any]:
    start = max(0, zone["index"] - cfg.leg_lookback_bars)
    leg = df_htf.iloc[start : zone["impulse_index"] + 1]
    leg_high = float(leg["high"].max())
    leg_low = float(leg["low"].min())
    equilibrium = (leg_high + leg_low) / 2.0
    zone_mid = (zone["top"] + zone["bottom"]) / 2.0
    in_discount = zone_mid < equilibrium
    in_premium = zone_mid > equilibrium
    return {
        "leg_high": leg_high, "leg_low": leg_low, "equilibrium": equilibrium,
        "zone_mid": zone_mid, "in_discount": in_discount, "in_premium": in_premium,
    }


# ---------------------------------------------------------------------------
# Filter 5 — Exit Test: untouched opposing HTF liquidity ahead, with room
# ---------------------------------------------------------------------------

def target_liquidity(df_htf: pd.DataFrame, zone: dict[str, Any], cfg: FiveFilterConfig) -> dict[str, Any] | None:
    swung = _swing_columns(df_htf, cfg.swing_window)
    zi = zone["index"]
    after = swung.iloc[zi:]

    if zone["bullish"]:
        candidates = after["swing_high"].dropna()
        for idx, level in candidates.items():
            pos = df_htf.index.get_loc(idx)
            untouched = not bool((df_htf["high"].iloc[pos + 1 :] > level).any())
            if untouched:
                return {"level": float(level)}
        return None

    candidates = after["swing_low"].dropna()
    for idx, level in candidates.items():
        pos = df_htf.index.get_loc(idx)
        untouched = not bool((df_htf["low"].iloc[pos + 1 :] < level).any())
        if untouched:
            return {"level": float(level)}
    return None


# ---------------------------------------------------------------------------
# LTF entry-model confirmation
# ---------------------------------------------------------------------------

def _ltf_choch_confirmed(df_ltf: pd.DataFrame, direction: str, tap_index: int, swing_window: int) -> int | None:
    """Returns the LTF bar index where a structure shift confirmed the
    reversal, or None if not yet confirmed."""
    swung = _swing_columns(df_ltf, max(3, swing_window - 2))
    after = swung.iloc[tap_index:]
    if direction == "LONG":
        highs = after["swing_high"].dropna()
        if highs.empty:
            return None
        level = float(highs.iloc[0])
        broke = df_ltf.iloc[tap_index:][df_ltf["close"].iloc[tap_index:] > level]
        return df_ltf.index.get_loc(broke.index[0]) if not broke.empty else None
    lows = after["swing_low"].dropna()
    if lows.empty:
        return None
    level = float(lows.iloc[0])
    broke = df_ltf.iloc[tap_index:][df_ltf["close"].iloc[tap_index:] < level]
    return df_ltf.index.get_loc(broke.index[0]) if not broke.empty else None


def _ltf_fvg_after(df_ltf: pd.DataFrame, direction: str, since_index: int) -> bool:
    """Ultra-Conservative's stacked second confirmation: a same-direction
    continuation FVG forming after the ChoCh."""
    end = len(df_ltf)
    for k in range(max(since_index + 2, 2), end):
        if direction == "LONG" and df_ltf["low"].iloc[k] > df_ltf["high"].iloc[k - 2]:
            return True
        if direction == "SHORT" and df_ltf["high"].iloc[k] < df_ltf["low"].iloc[k - 2]:
            return True
    return False


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_five_filter_pipeline(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, cfg: FiveFilterConfig) -> dict[str, Any]:
    ltf = normalize_ohlcv(df_ltf)
    htf = normalize_ohlcv(df_htf)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.ltf} data."}
    if htf.empty or len(htf) < max(cfg.leg_lookback_bars // 2, 20):
        return {"error": f"Insufficient {cfg.htf} data."}
    return {"ltf": ltf, "htf": htf}


def evaluate_live_signal(pipeline: dict[str, Any], cfg: FiveFilterConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    ltf, htf = pipeline["ltf"], pipeline["htf"]
    price = float(ltf["close"].iloc[-1])

    filters: list[dict[str, Any]] = []
    reasons: list[str] = []
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "NO_SETUP"
    conf = 15.0
    entry, stop, target = price, price, price

    zone = find_unmitigated_zone(htf, cfg)
    p1 = zone is not None
    filters.append({"name": "Permission", "passed": p1, "detail": (
        f"Unmitigated {'demand' if zone and zone['bullish'] else 'supply'} zone at "
        f"{zone['bottom']:,.4g}–{zone['top']:,.4g} on {cfg.htf} — {'buys' if zone and zone['bullish'] else 'sells'} only."
        if p1 else f"No unmitigated HTF ({cfg.htf}) supply/demand zone found in the last {cfg.zone_lookback_bars} bars — no permission to trade either side."
    )})

    sweep = footprint = fvg = location = exit_test = None
    if p1:
        direction = "LONG" if zone["bullish"] else "SHORT"

        sweep = sweep_before_zone(htf, zone, cfg)
        p2 = sweep is not None
        filters.append({"name": "Footprint", "passed": p2, "detail": (
            f"Zone origin followed a {sweep['direction'].replace('_', ' ')} liquidity sweep of {sweep['level']:,.4g} — the true smart-money footprint."
            if p2 else "Zone origin wasn't preceded by a validated liquidity sweep of a prior swing — could be random consolidation, not smart money."
        )})

        fvg = fvg_in_zone_leg(htf, zone)
        p3 = bool(fvg and not fvg["filled"])
        filters.append({"name": "Inefficiency", "passed": p3, "detail": (
            f"Unfilled Fair Value Gap at {fvg['bottom']:,.4g}–{fvg['top']:,.4g} sits in the same leg — the zone is still magnetic."
            if p3 else "No unfilled Fair Value Gap in this leg — the zone lacks the imbalance that makes it sensitive."
        )})

        location = leg_discount_premium(htf, zone, cfg)
        p4 = location["in_discount"] if direction == "LONG" else location["in_premium"]
        filters.append({"name": "Location", "passed": p4, "detail": (
            f"Zone sits in the {'discount' if direction == 'LONG' else 'premium'} half of the leg "
            f"({location['leg_low']:,.4g}–{location['leg_high']:,.4g}, eq {location['equilibrium']:,.4g})."
            if p4 else f"Zone sits too close to (or past) the midpoint of the range ({location['equilibrium']:,.4g}) — not {'discount' if direction == 'LONG' else 'premium'} enough to trust."
        )})

        exit_test = target_liquidity(htf, zone, cfg)
        prospective_stop = zone["bottom"] if direction == "LONG" else zone["top"]
        prospective_entry = (zone["top"] + zone["bottom"]) / 2.0
        risk = abs(prospective_entry - prospective_stop) or max(price * 0.002, 0.01)
        rr = None
        if exit_test:
            reward = abs(exit_test["level"] - prospective_entry)
            rr = reward / risk if risk else 0.0
        p5 = bool(exit_test and rr is not None and rr >= cfg.min_rr_ratio)
        filters.append({"name": "Exit Test", "passed": p5, "detail": (
            f"Untouched liquidity resting at {exit_test['level']:,.4g} gives {rr:.1f}R of room — worth the risk."
            if p5 and exit_test else
            (f"Nearest liquidity target only offers {rr:.1f}R (need {cfg.min_rr_ratio:.1f}R) — not enough room to justify the risk."
             if exit_test else "No untouched higher-timeframe liquidity ahead of price — no clear target, stay out.")
        )})
    else:
        for name in FILTER_NAMES[1:]:
            filters.append({"name": name, "passed": False, "detail": "Skipped — Filter 1 (Permission) already failed."})

    all_passed = all(f["passed"] for f in filters)
    passed_count = sum(1 for f in filters if f["passed"])
    conf = 15.0 + passed_count * 12.0

    if not all_passed:
        verdict = "NO_SETUP" if not p1 else "SKIP"
        reasons = [f"{f['name']}: {f['detail']}" for f in filters]
        conf = min(conf, 55.0)
    else:
        phase = PHASE_CONFIRMED
        zone_top, zone_bottom = zone["top"], zone["bottom"]
        entry = (zone_top + zone_bottom) / 2.0
        stop = zone_bottom if direction == "LONG" else zone_top
        target = exit_test["level"]
        reasons = [f"✅ {f['name']}: {f['detail']}" for f in filters]
        reasons.append("All 5 filters passed — this is an A+ setup per the strategy's own standard.")

        tapped = bool(((ltf["low"] <= zone_top) & (ltf["high"] >= zone_bottom)).any())
        tap_positions = ltf.index[(ltf["low"] <= zone_top) & (ltf["high"] >= zone_bottom)]
        tap_pos = ltf.index.get_loc(tap_positions[0]) if len(tap_positions) else None

        if not tapped:
            verdict = f"WATCH {direction}"
            reasons.append(f"Waiting for price to pull back into the zone ({zone_bottom:,.4g}–{zone_top:,.4g}).")
        elif cfg.entry_model == "Aggressive":
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            conf += 18
            reasons.append("Aggressive entry: price is inside the zone — entering now at the zone midpoint.")
        else:
            choch_idx = _ltf_choch_confirmed(ltf, direction, tap_pos or 0, cfg.swing_window)
            if choch_idx is None:
                verdict = f"WATCH {direction}"
                reasons.append(f"Price tapped the zone — waiting for an LTF ({cfg.ltf}) Change of Character to confirm before entry.")
            elif cfg.entry_model == "Conservative":
                phase = PHASE_ENTRY
                verdict = f"TAKE {direction}"
                conf += 22
                entry = price
                reasons.append(f"Conservative entry: price tapped the zone AND an LTF ({cfg.ltf}) Change of Character confirmed the reversal.")
            else:  # Ultra-Conservative
                if _ltf_fvg_after(ltf, direction, choch_idx):
                    phase = PHASE_ENTRY
                    verdict = f"TAKE {direction}"
                    conf += 26
                    entry = price
                    reasons.append(f"Ultra-Conservative entry: LTF ChoCh confirmed AND a same-direction continuation FVG stacked on top — maximum confirmation.")
                else:
                    verdict = f"WATCH {direction}"
                    reasons.append("LTF Change of Character confirmed, but Ultra-Conservative mode is waiting for a stacked continuation FVG before entering.")

    conf = max(10.0, min(95.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < entry:
        sl_pct = max(0.15, (entry - stop) / entry * 100)
        tp_pct = max(0.2, (target - entry) / entry * 100) if target > entry else sl_pct * cfg.rr_ratio_fallback
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.15, (stop - entry) / entry * 100)
        tp_pct = max(0.2, (entry - target) / entry * 100) if target < entry else sl_pct * cfg.rr_ratio_fallback
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio_fallback

    hold = hold_for_tf(cfg.ltf, "intraday" if cfg.ltf in ("1m", "5m", "15m", "30m") else "swing")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Target = the Exit Test's HTF liquidity level. Exit if price closes beyond the zone stop (setup invalidated).",
        max_hold_exit=f"Time stop per {cfg.ltf} window if neither SL nor TP hits.",
    )

    return enrich_smc_live({
        "signal": direction if phase == PHASE_ENTRY else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "entry_model": cfg.entry_model,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "filters": filters,
        "filters_passed": passed_count,
        "filters_total": len(FILTER_NAMES),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: FiveFilterConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    df_ltf = fetch_data_for_gap_scan(ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars)
    df_ltf = normalize_ohlcv(df_ltf)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        df_ltf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )

    df_htf = fetch_data_for_gap_scan(ticker, cfg.htf, market, groww_token, exchange, limit=max(150, cfg.lookback_bars // 4))
    df_htf = normalize_ohlcv(df_htf)
    if df_htf.empty:
        df_htf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.htf, is_crypto=is_crypto, limit=max(150, cfg.lookback_bars // 4), market=market),
        )

    return df_ltf, df_htf


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: FiveFilterConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or FiveFilterConfig()
    df_ltf, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data."}
    if df_htf.empty:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data."}

    pipeline = run_five_filter_pipeline(df_ltf, df_htf, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "bars_htf": len(pipeline["htf"]),
        "bars_ltf": len(pipeline["ltf"]),
        "last_close": float(pipeline["ltf"]["close"].iloc[-1]),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: FiveFilterConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = False,
) -> dict[str, Any]:
    cfg = cfg or FiveFilterConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
