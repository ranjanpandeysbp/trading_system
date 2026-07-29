"""
support_resistance_engine.py
------------------------------
Support and Resistance — break-and-retest zones on a higher timeframe, entry
confirmation via market structure on a lower timeframe. Works across Groww
India, US, Crypto, and Commodities (the standard market/groww_token/exchange
plumbing every hub section already gets).
https://www.youtube.com/watch?v=d5T-k_-ejd0&t=29s

The method, in order:
1. Zones, not lines — on the HTF, a resistance zone runs from the highest
   wick down to the highest candle body in a rejection cluster; a support
   zone runs from the lowest wick up to the lowest body. Price reacts to a
   zone, not an exact price.
2. Break and retest — a resistance zone that gets strongly broken above
   becomes a new support zone the next time price returns to it (and the
   mirror image for a broken support zone becoming resistance).
3. Alert, don't stare — nothing happens until price actually taps back into
   a zone.
4. Lower-timeframe confirmation — once tapped, drop to the LTF and read
   market structure. Approaching support, price should be making lower
   highs/lows; the trigger is a clean break above the most recent LTF lower
   high (the mirror image at resistance: break below the most recent higher
   low). Never enter on the tap alone.
5. Entry at the structure break; stop beyond the zone (or the pre-entry
   extreme); target the next recent structural high/low.
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

YOUTUBE_SUPPORT_RESISTANCE_URL = "https://www.youtube.com/watch?v=d5T-k_-ejd0&t=29s"

HTF_OPTIONS = ["1h", "4h", "1d"]
LTF_OPTIONS = ["1m", "5m", "15m"]

PHASE_NONE = "NO_SETUP"
PHASE_ZONE_TAPPED = "ZONE_TAPPED"
PHASE_ENTRY = "STRUCTURE_BREAK_ENTRY"


@dataclass
class SupportResistanceConfig:
    htf: str = "4h"
    ltf: str = "1m"
    zone_lookback_bars: int = 100
    swing_window: int = 3
    zone_tap_buffer_pct: float = 0.1
    rr_ratio_fallback: float = 2.0
    max_setup_age_bars: int = 40
    take_confidence_threshold: float = 60.0
    min_bars: int = 80
    lookback_bars: int = 500


# ---------------------------------------------------------------------------
# Shared low-level helpers (self-contained, matching the style of the other
# hub engines rather than a shared library)
# ---------------------------------------------------------------------------

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
# Step 1-2: HTF zones + break-and-retest role flip
# ---------------------------------------------------------------------------

def _zone_from_swing(df: pd.DataFrame, idx: int, is_high: bool) -> dict[str, Any]:
    """Zone = wick extreme to body extreme of the swing bar (a 1-bar
    rejection cluster keeps this simple and robust across timeframes)."""
    bar = df.iloc[idx]
    body_top = max(bar["open"], bar["close"])
    body_bottom = min(bar["open"], bar["close"])
    if is_high:
        return {"top": float(bar["high"]), "bottom": float(body_top), "origin_index": idx}
    return {"top": float(body_bottom), "bottom": float(bar["low"]), "origin_index": idx}


def find_active_zones(df_htf: pd.DataFrame, cfg: SupportResistanceConfig) -> dict[str, dict[str, Any] | None]:
    """Latest active support zone (below price) and resistance zone (above
    price) — each may be an original zone, or an opposite zone that's been
    broken-and-flipped per the break-and-retest rule."""
    swung = _swing_columns(df_htf, cfg.swing_window)
    n = len(df_htf)
    start = max(0, n - cfg.zone_lookback_bars)
    price = float(df_htf["close"].iloc[-1])
    closes = df_htf["close"].values

    candidates: list[dict[str, Any]] = []
    for i in range(start, n):
        if not pd.isna(swung["swing_high"].iloc[i]):
            zone = _zone_from_swing(df_htf, i, is_high=True)
            role = "resistance"
            # Broken upward since formation -> flips to support.
            after = closes[i + 1 :]
            if len(after) and after.max() > zone["top"]:
                role = "support"
            candidates.append({**zone, "role": role, "kind": "swing_high"})
        if not pd.isna(swung["swing_low"].iloc[i]):
            zone = _zone_from_swing(df_htf, i, is_high=False)
            role = "support"
            after = closes[i + 1 :]
            if len(after) and after.min() < zone["bottom"]:
                role = "resistance"
            candidates.append({**zone, "role": role, "kind": "swing_low"})

    support = None
    resistance = None
    for z in sorted(candidates, key=lambda z: -z["origin_index"]):
        if z["role"] == "support" and z["top"] <= price and support is None:
            support = z
        elif z["role"] == "resistance" and z["bottom"] >= price and resistance is None:
            resistance = z
        if support and resistance:
            break

    return {"support": support, "resistance": resistance}


# ---------------------------------------------------------------------------
# Step 4: LTF market-structure-break confirmation after a zone tap
# ---------------------------------------------------------------------------

def _structure_break_after_tap(df_ltf: pd.DataFrame, direction: str, tap_index: int, swing_window: int) -> int | None:
    swung = _swing_columns(df_ltf, max(3, swing_window - 1))
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


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_sr_pipeline(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, cfg: SupportResistanceConfig) -> dict[str, Any]:
    ltf = normalize_ohlcv(df_ltf)
    htf = normalize_ohlcv(df_htf)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.ltf} data."}
    if htf.empty or len(htf) < max(cfg.swing_window * 4, 20):
        return {"error": f"Insufficient {cfg.htf} data."}
    return {"ltf": ltf, "htf": htf}


def evaluate_live_signal(pipeline: dict[str, Any], cfg: SupportResistanceConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    ltf, htf = pipeline["ltf"], pipeline["htf"]
    price = float(ltf["close"].iloc[-1])
    zones = find_active_zones(htf, cfg)
    support, resistance = zones["support"], zones["resistance"]

    reasons: list[str] = []
    if support:
        flipped = " (flipped from a broken resistance zone — break-and-retest)" if support.get("kind") == "swing_high" else ""
        reasons.append(f"Support zone{flipped} at {support['bottom']:,.4g}–{support['top']:,.4g} on {cfg.htf}.")
    else:
        reasons.append(f"No support zone found below price in the last {cfg.zone_lookback_bars} {cfg.htf} bars.")
    if resistance:
        flipped_r = " (flipped from a broken support zone — break-and-retest)" if resistance.get("kind") == "swing_low" else ""
        reasons.append(f"Resistance zone{flipped_r} at {resistance['bottom']:,.4g}–{resistance['top']:,.4g} on {cfg.htf}.")
    else:
        reasons.append(f"No resistance zone found above price in the last {cfg.zone_lookback_bars} {cfg.htf} bars.")

    buffer_support = (support["top"] - support["bottom"]) * cfg.zone_tap_buffer_pct if support else 0
    buffer_resistance = (resistance["top"] - resistance["bottom"]) * cfg.zone_tap_buffer_pct if resistance else 0

    tapping_support = bool(support and support["bottom"] - buffer_support <= price <= support["top"] + buffer_support)
    tapping_resistance = bool(resistance and resistance["bottom"] - buffer_resistance <= price <= resistance["top"] + buffer_resistance)

    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "NO_SETUP"
    conf = 20.0
    entry, stop, target = price, price, price
    zone = None

    if tapping_support:
        direction, zone = "LONG", support
    elif tapping_resistance:
        direction, zone = "SHORT", resistance

    if zone is None:
        take = False
    else:
        phase = PHASE_ZONE_TAPPED
        conf += 20
        reasons.append(f"Price has tapped into the {'support' if direction == 'LONG' else 'resistance'} zone — waiting for a lower-timeframe structure break to confirm, per the strategy's own rule against entering on the tap alone.")

        # Find the tap bar on the LTF to anchor the structure-break search.
        z_top, z_bottom = zone["top"] + (buffer_support if direction == "LONG" else buffer_resistance), zone["bottom"] - (buffer_support if direction == "LONG" else buffer_resistance)
        tap_mask = (ltf["low"] <= z_top) & (ltf["high"] >= z_bottom)
        tap_positions = ltf.index[tap_mask]
        tap_pos = ltf.index.get_loc(tap_positions[0]) if len(tap_positions) else max(0, len(ltf) - cfg.max_setup_age_bars)

        break_idx = _structure_break_after_tap(ltf, direction, tap_pos, cfg.swing_window)
        if break_idx is None:
            verdict = f"WATCH {direction}"
            reasons.append(f"No LTF ({cfg.ltf}) structure break yet — still waiting for the clean break of the most recent {'lower high' if direction == 'LONG' else 'higher low'}.")
        else:
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            conf += 30
            entry = price
            stop = zone["bottom"] - buffer_support if direction == "LONG" else zone["top"] + buffer_resistance
            opposing = resistance if direction == "LONG" else support
            if opposing:
                target = opposing["bottom"] if direction == "LONG" else opposing["top"]
            else:
                risk = abs(entry - stop) or max(price * 0.005, 0.01)
                target = entry + risk * cfg.rr_ratio_fallback if direction == "LONG" else entry - risk * cfg.rr_ratio_fallback
            reasons.append(
                f"LTF ({cfg.ltf}) market structure broke {'above the most recent lower high' if direction == 'LONG' else 'below the most recent higher low'} — entry triggered, stop beyond the zone, target the next structural {'high' if direction == 'LONG' else 'low'}."
            )
        take = phase == PHASE_ENTRY

    conf = max(10.0, min(90.0, conf))
    take = take and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < entry:
        sl_pct = max(0.15, (entry - stop) / entry * 100)
        tp_pct = max(0.2, (target - entry) / entry * 100) if target > entry else sl_pct * cfg.rr_ratio_fallback
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.15, (stop - entry) / entry * 100)
        tp_pct = max(0.2, (entry - target) / entry * 100) if target < entry else sl_pct * cfg.rr_ratio_fallback
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio_fallback

    hold = hold_for_tf(cfg.ltf, "intraday" if cfg.ltf in ("1m", "5m", "15m") else "swing")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="Target the next recent structural high/low. Exit if price closes back beyond the zone (setup invalidated).",
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
        "support_zone": [round(support["bottom"], 6), round(support["top"], 6)] if support else None,
        "resistance_zone": [round(resistance["bottom"], 6), round(resistance["top"], 6)] if resistance else None,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: SupportResistanceConfig,
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
    cfg: SupportResistanceConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SupportResistanceConfig()
    df_ltf, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data."}
    if df_htf.empty:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data."}

    pipeline = run_sr_pipeline(df_ltf, df_htf, cfg)
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
    cfg: SupportResistanceConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = False,
) -> dict[str, Any]:
    cfg = cfg or SupportResistanceConfig()
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
