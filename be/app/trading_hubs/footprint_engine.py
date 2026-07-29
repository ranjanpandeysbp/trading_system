"""
footprint_engine.py
--------------------
Footprint — order-flow confirmation at key support/resistance levels.
https://www.youtube.com/watch?v=kcglxDJ_ZF0

This app's data sources (Groww/yfinance/CoinDCX) provide OHLCV bars, not
literal bid/ask tick-level footprint data. Buy/sell volume per bar is
therefore ESTIMATED from where each candle's close sits within its own
high-low range (the same money-flow-multiplier style delta proxy already
used by the Scanner's `orderflow_imbalance_scalp` strategy) — an honest
approximation of order flow, not a claim of real Level 2 data.

The 3-step framework, applied at a key HTF support/resistance zone:
1. Delta       — buyers minus (estimated) sellers. Positive = aggressive
                 buying, negative = aggressive selling. Price up on negative
                 delta (or vice versa) is exhaustion — big money quietly
                 fading the move.
2. Imbalances  — a bar where one side overwhelms the other (this engine's
                 threshold: one side at least `imbalance_ratio`x the other).
                 Three or more of these stacked in the same direction is
                 treated as an institutional "fingerprint" carving out a
                 tighter zone inside the broader HTF level.
3. Absorption  — high volume and a large delta magnitude, but the price
                 barely moves (a small body relative to ATR) — an invisible
                 wall quietly absorbing the aggressive side, one of the
                 strongest reversal tells when it happens at a key level.

Entry requires the full order of operations: Delta must favor the reversal
direction, a stacked imbalance run in that direction must be present, and an
absorption bar must confirm it — all at the same HTF zone.
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

YOUTUBE_FOOTPRINT_URL = "https://www.youtube.com/watch?v=kcglxDJ_ZF0"

HTF_OPTIONS = ["1h", "4h", "1d"]
LTF_OPTIONS = ["1m", "5m", "15m"]

PHASE_NONE = "NO_SETUP"
PHASE_ZONE_TAPPED = "ZONE_TAPPED"
PHASE_ENTRY = "ORDER_FLOW_CONFIRMED"


@dataclass
class FootprintConfig:
    htf: str = "4h"
    ltf: str = "5m"
    zone_lookback_bars: int = 100
    swing_window: int = 3
    zone_tap_buffer_pct: float = 0.1
    imbalance_ratio: float = 3.0
    min_stacked_imbalances: int = 3
    imbalance_scan_bars: int = 12
    delta_lookback_bars: int = 5
    absorption_lookback_bars: int = 8
    absorption_volume_z: float = 1.25
    absorption_max_body_atr_mult: float = 0.5
    rr_ratio_fallback: float = 2.0
    take_confidence_threshold: float = 60.0
    min_bars: int = 80
    lookback_bars: int = 500


# ---------------------------------------------------------------------------
# Shared low-level helpers (self-contained, matching the style of the other
# hub engines rather than a shared library)
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


def _zone_from_swing(df: pd.DataFrame, idx: int, is_high: bool) -> dict[str, Any]:
    bar = df.iloc[idx]
    body_top = max(bar["open"], bar["close"])
    body_bottom = min(bar["open"], bar["close"])
    if is_high:
        return {"top": float(bar["high"]), "bottom": float(body_top), "origin_index": idx}
    return {"top": float(body_bottom), "bottom": float(bar["low"]), "origin_index": idx}


def find_active_zones(df_htf: pd.DataFrame, cfg: FootprintConfig) -> dict[str, dict[str, Any] | None]:
    """Nearest key support/resistance zones, with break-and-retest role
    flip — the levels footprint confirmation is applied at."""
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
            after = closes[i + 1 :]
            if len(after) and after.max() > zone["top"]:
                role = "support"
            candidates.append({**zone, "role": role})
        if not pd.isna(swung["swing_low"].iloc[i]):
            zone = _zone_from_swing(df_htf, i, is_high=False)
            role = "support"
            after = closes[i + 1 :]
            if len(after) and after.min() < zone["bottom"]:
                role = "resistance"
            candidates.append({**zone, "role": role})

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
# Order-flow proxy: per-bar buy/sell volume, delta, imbalance, absorption
# ---------------------------------------------------------------------------

def compute_order_flow(df: pd.DataFrame, cfg: FootprintConfig) -> pd.DataFrame:
    out = df.copy()
    rng = (out["high"] - out["low"]).replace(0, np.nan)
    buy_frac = ((out["close"] - out["low"]) / rng).clip(0, 1).fillna(0.5)
    out["buy_vol"] = out["volume"] * buy_frac
    out["sell_vol"] = out["volume"] * (1 - buy_frac)
    out["delta"] = out["buy_vol"] - out["sell_vol"]

    eps = 1e-9
    ratio = out["buy_vol"] / out["sell_vol"].clip(lower=eps)
    out["imbalance_dir"] = np.where(
        ratio >= cfg.imbalance_ratio, "buy",
        np.where(out["sell_vol"] / out["buy_vol"].clip(lower=eps) >= cfg.imbalance_ratio, "sell", "")
    )

    atr = _atr(out, 14)
    body = (out["close"] - out["open"]).abs()
    vol_mean = out["volume"].rolling(30, min_periods=10).mean()
    vol_std = out["volume"].rolling(30, min_periods=10).std()
    out["volume_z"] = (out["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    out["is_absorption"] = (
        (out["volume_z"] >= cfg.absorption_volume_z)
        & (body <= atr * cfg.absorption_max_body_atr_mult)
        & (out["delta"].abs() > 0)
    )
    return out


def find_stacked_imbalance(df: pd.DataFrame, cfg: FootprintConfig) -> dict[str, Any] | None:
    """Most recent run of `min_stacked_imbalances`+ consecutive same-direction
    imbalance bars within the scan window — the institutional "fingerprint"."""
    window = df.iloc[-cfg.imbalance_scan_bars :]
    dirs = window["imbalance_dir"].tolist()

    best: dict[str, Any] | None = None
    run_dir, run_start = "", 0
    for i, d in enumerate(dirs):
        if d and d == run_dir:
            continue
        if run_dir and (i - run_start) >= cfg.min_stacked_imbalances:
            seg = window.iloc[run_start:i]
            best = {
                "direction": run_dir,
                "count": i - run_start,
                "top": float(seg["high"].max()),
                "bottom": float(seg["low"].min()),
            }
        run_dir, run_start = d, i
    if run_dir and (len(dirs) - run_start) >= cfg.min_stacked_imbalances:
        seg = window.iloc[run_start:]
        best = {
            "direction": run_dir,
            "count": len(dirs) - run_start,
            "top": float(seg["high"].max()),
            "bottom": float(seg["low"].min()),
        }
    return best


def find_absorption(df: pd.DataFrame, cfg: FootprintConfig) -> dict[str, Any] | None:
    window = df.iloc[-cfg.absorption_lookback_bars :]
    hits = window[window["is_absorption"]]
    if hits.empty:
        return None
    bar = hits.iloc[-1]
    return {
        "direction": "sell" if bar["delta"] < 0 else "buy",
        "price": float(bar["close"]),
        "volume_z": float(bar["volume_z"]),
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_footprint_pipeline(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, cfg: FootprintConfig) -> dict[str, Any]:
    ltf = normalize_ohlcv(df_ltf)
    htf = normalize_ohlcv(df_htf)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.ltf} data."}
    if htf.empty or len(htf) < max(cfg.swing_window * 4, 20):
        return {"error": f"Insufficient {cfg.htf} data."}
    return {"ltf": compute_order_flow(ltf, cfg), "htf": htf}


def evaluate_live_signal(pipeline: dict[str, Any], cfg: FootprintConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    ltf, htf = pipeline["ltf"], pipeline["htf"]
    price = float(ltf["close"].iloc[-1])
    zones = find_active_zones(htf, cfg)
    support, resistance = zones["support"], zones["resistance"]

    reasons: list[str] = []
    if support:
        reasons.append(f"Support zone at {support['bottom']:,.4g}–{support['top']:,.4g} on {cfg.htf}.")
    if resistance:
        reasons.append(f"Resistance zone at {resistance['bottom']:,.4g}–{resistance['top']:,.4g} on {cfg.htf}.")

    buf_s = (support["top"] - support["bottom"]) * cfg.zone_tap_buffer_pct if support else 0
    buf_r = (resistance["top"] - resistance["bottom"]) * cfg.zone_tap_buffer_pct if resistance else 0
    tapping_support = bool(support and support["bottom"] - buf_s <= price <= support["top"] + buf_s)
    tapping_resistance = bool(resistance and resistance["bottom"] - buf_r <= price <= resistance["top"] + buf_r)

    direction = "WAIT"
    zone = None
    if tapping_support:
        direction, zone = "LONG", support
    elif tapping_resistance:
        direction, zone = "SHORT", resistance

    phase = PHASE_NONE
    verdict = "NO_SETUP"
    conf = 20.0
    entry, stop, target = price, price, price
    take = False

    if zone is None:
        reasons.append("Price isn't at a key support/resistance level right now — footprint is a confirmation tool, not a standalone trigger.")
    else:
        phase = PHASE_ZONE_TAPPED
        wanted_delta = "buy" if direction == "LONG" else "sell"

        # Step 1 — Delta: who won the recent bars approaching the zone.
        recent = ltf.iloc[-cfg.delta_lookback_bars :]
        cum_delta = float(recent["delta"].sum())
        delta_ok = cum_delta > 0 if direction == "LONG" else cum_delta < 0
        reasons.append(
            f"Step 1 — Delta: last {cfg.delta_lookback_bars} bars netted {cum_delta:,.4g} "
            f"({'buyers' if cum_delta > 0 else 'sellers'} winning) — "
            f"{'favors' if delta_ok else 'does not favor'} {direction}."
        )
        if delta_ok:
            conf += 15

        # Step 2 — Imbalances: 3+ stacked same-direction imbalance bars.
        imbalance = find_stacked_imbalance(ltf, cfg)
        imbalance_ok = bool(imbalance and imbalance["direction"] == wanted_delta)
        if imbalance:
            reasons.append(
                f"Step 2 — Imbalances: {imbalance['count']} stacked {imbalance['direction']}-side imbalance bars "
                f"({imbalance['bottom']:,.4g}–{imbalance['top']:,.4g}) — "
                f"{'a fingerprint in this direction' if imbalance_ok else 'wrong direction for this setup'}."
            )
        else:
            reasons.append(f"Step 2 — Imbalances: no run of {cfg.min_stacked_imbalances}+ stacked one-sided bars found yet.")
        if imbalance_ok:
            conf += 20

        # Step 3 — Absorption: high volume/delta, price goes nowhere.
        absorption = find_absorption(ltf, cfg)
        absorption_ok = bool(absorption and absorption["direction"] == ("sell" if direction == "LONG" else "buy"))
        if absorption:
            reasons.append(
                f"Step 3 — Absorption: a high-volume ({absorption['volume_z']:.1f}σ) small-body bar absorbed "
                f"{'selling' if absorption['direction'] == 'sell' else 'buying'} pressure near {absorption['price']:,.4g} — "
                f"{'confirms' if absorption_ok else 'wrong side for'} the reversal."
            )
        else:
            reasons.append("Step 3 — Absorption: no high-volume, small-body absorption bar found near the zone yet.")
        if absorption_ok:
            conf += 25

        if delta_ok and imbalance_ok and absorption_ok:
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            entry = price
            stop = zone["bottom"] - buf_s if direction == "LONG" else zone["top"] + buf_r
            opposing = resistance if direction == "LONG" else support
            if opposing:
                target = opposing["bottom"] if direction == "LONG" else opposing["top"]
            else:
                risk = abs(entry - stop) or max(price * 0.005, 0.01)
                target = entry + risk * cfg.rr_ratio_fallback if direction == "LONG" else entry - risk * cfg.rr_ratio_fallback
            reasons.append("All 3 steps confirm — order flow supports this trade at a key level.")
        else:
            verdict = f"WATCH {direction}"
            missing = [n for n, ok in (("Delta", delta_ok), ("Imbalances", imbalance_ok), ("Absorption", absorption_ok)) if not ok]
            reasons.append(f"Waiting on: {', '.join(missing)} before this is a confirmed setup.")

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
        style="intraday",
        exit_rule="Target the opposing key level. Exit if price closes back beyond the zone (setup invalidated).",
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
    cfg: FootprintConfig,
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
    cfg: FootprintConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or FootprintConfig()
    df_ltf, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data."}
    if df_htf.empty:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data."}

    pipeline = run_footprint_pipeline(df_ltf, df_htf, cfg)
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
    cfg: FootprintConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = False,
) -> dict[str, Any]:
    cfg = cfg or FootprintConfig()
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
