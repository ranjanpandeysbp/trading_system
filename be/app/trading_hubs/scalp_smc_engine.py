"""
scalp_smc_engine.py
-------------------
SMC scalping engine — Rule of Three TFs, premium/discount/OTE, FVG, OB, CRT sweeps.

Integrated from modular SMC engine (fractal structure, displacement OBs, signal fusion).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
from app.trading_hubs.smc_engine.config import SMCConfig
from app.trading_hubs.smc_engine.data import build_multi_timeframe
from app.trading_hubs.smc_engine.imbalances import detect_fvgs, detect_order_blocks
from app.trading_hubs.smc_engine.liquidity import detect_crt_sweeps
from app.trading_hubs.smc_engine.models import Bias, TradeSetup
from app.trading_hubs.smc_engine.signals import generate_trade_setups
from app.trading_hubs.smc_engine.structure import (
    current_bias,
    detect_structure_breaks,
    find_fractal_swings,
)
from app.trading_hubs.smc_engine.zones import build_trade_zone, price_is_in_discount, price_is_in_ote, price_is_in_premium
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_SMC_URL = "https://www.youtube.com/watch?v=8avLqVtKAhk&t=257s"

LTF_OPTIONS = ["1m", "5m", "15m"]
PHASE_NONE = "NO_SETUP"
PHASE_IN_ZONE = "IN_ZONE"
PHASE_OTE = "IN_OTE"
PHASE_CONFIRMED = "SMC_ENTRY"

_TF_RESAMPLE = {
    "1m": ("15min", "1h"),
    "5m": ("1h", "4h"),
    "15m": ("1h", "4h"),
}


@dataclass
class ScalpSMCConfig:
    ltf: str = "5m"
    fractal_window: int = 2
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 62.0
    min_ltf_bars: int = 120
    lookback_bars: int = 600
    displacement_multiplier: float = 1.5
    recent_setup_bars: int = 8


def _smc_config(cfg: ScalpSMCConfig) -> SMCConfig:
    mtf_rule, htf_rule = _TF_RESAMPLE.get(cfg.ltf, ("1h", "4h"))
    return SMCConfig(
        fractal_window=cfg.fractal_window,
        displacement_multiplier=cfg.displacement_multiplier,
        mtf_rule=mtf_rule,
        htf_rule=htf_rule,
    )


def run_smc_pipeline(df_ltf_raw: pd.DataFrame, cfg: ScalpSMCConfig) -> dict[str, Any]:
    """HTF structure + zone; LTF FVG/OB/CRT; fused trade setups."""
    smc_cfg = _smc_config(cfg)
    df_ltf = to_smc_ohlc(df_ltf_raw)
    if df_ltf.empty or len(df_ltf) < cfg.min_ltf_bars:
        return {"error": "Insufficient LTF bars."}

    timeframes = build_multi_timeframe(df_ltf, smc_cfg)
    df_htf = timeframes["HTF"]
    if df_htf.empty or len(df_htf) < 10:
        return {"error": "Insufficient HTF bars after resample."}

    htf_swings = find_fractal_swings(df_htf, smc_cfg.fractal_window)
    htf_breaks = detect_structure_breaks(df_htf, htf_swings)
    bias = current_bias(htf_breaks)
    zone = build_trade_zone(htf_swings, smc_cfg)

    fvgs = detect_fvgs(df_ltf, smc_cfg)
    order_blocks = detect_order_blocks(df_ltf, smc_cfg)
    sweeps = detect_crt_sweeps(df_ltf, smc_cfg)

    leg_start_time = None
    if zone is not None:
        leg_idx = min(zone.leg_start_index, zone.leg_end_index)
        if 0 <= leg_idx < len(df_htf):
            leg_start_time = df_htf.index[leg_idx]

    setups = generate_trade_setups(
        df_ltf, zone, bias, fvgs, order_blocks, sweeps, smc_cfg, leg_start_time=leg_start_time,
    ) if zone is not None else []

    return {
        "df_ltf": df_ltf,
        "df_htf": df_htf,
        "df_mtf": timeframes["MTF"],
        "swings": htf_swings,
        "breaks": htf_breaks,
        "bias": bias,
        "zone": zone,
        "fvgs": fvgs,
        "order_blocks": order_blocks,
        "sweeps": sweeps,
        "setups": setups,
    }


def _latest_setup(setups: list[TradeSetup], n_bars: int, ltf_len: int) -> TradeSetup | None:
    if not setups:
        return None
    cutoff = max(0, ltf_len - n_bars)
    recent = [s for s in setups if s.index >= cutoff]
    return recent[-1] if recent else setups[-1]


def _setup_history(setups: list[TradeSetup], limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for s in reversed(setups):
        ts = s.timestamp
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "direction": s.direction.upper(),
            "zone": s.zone_type,
            "confirmation": s.confirmation[:48],
            "entry": round(s.entry_price, 4),
        })
        if len(rows) >= limit:
            break
    return rows


def evaluate_live_signal(
    pipeline: dict[str, Any],
    cfg: ScalpSMCConfig,
) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    df_ltf = pipeline["df_ltf"]
    zone = pipeline.get("zone")
    bias: Bias = pipeline.get("bias", Bias.NEUTRAL)
    setups: list[TradeSetup] = pipeline.get("setups") or []
    price = float(df_ltf["Close"].iloc[-1])

    reasons: list[str] = []
    conf = 20.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    stop = price
    target = price
    zone_type = "—"
    confirmation = "—"
    active_setup = _latest_setup(setups, cfg.recent_setup_bars, len(df_ltf))

    bias_label = bias.value.upper()
    if bias != Bias.NEUTRAL:
        conf += 16
        reasons.append(f"HTF structural bias: **{bias_label}** (BOS/CHoCH on resampled HTF)")

    if zone is not None:
        ote_lo, ote_hi = zone.ote_zone()
        reasons.append(
            f"Premium/Discount leg **{zone.leg_low:,.4g}–{zone.leg_high:,.4g}** · "
            f"EQ **{zone.equilibrium:,.4g}** · OTE **{ote_lo:,.4g}–{ote_hi:,.4g}**"
        )
        if bias == Bias.BULLISH and price_is_in_discount(price, zone):
            conf += 14
            phase = PHASE_OTE if price_is_in_ote(price, zone) else PHASE_IN_ZONE
            zone_type = "OTE" if price_is_in_ote(price, zone) else "Discount"
            direction = "LONG"
            reasons.append(f"Price in HTF **{zone_type}** zone (bullish context)")
        elif bias == Bias.BEARISH and price_is_in_premium(price, zone):
            conf += 14
            phase = PHASE_OTE if price_is_in_ote(price, zone) else PHASE_IN_ZONE
            zone_type = "OTE" if price_is_in_ote(price, zone) else "Premium"
            direction = "SHORT"
            reasons.append(f"Price in HTF **{zone_type}** zone (bearish context)")

    unmit_fvg = sum(1 for g in pipeline.get("fvgs", []) if not g.mitigated)
    unmit_ob = sum(1 for o in pipeline.get("order_blocks", []) if not o.mitigated)
    val_sweeps = sum(1 for s in pipeline.get("sweeps", []) if s.validated)
    if unmit_fvg:
        conf += min(8, unmit_fvg * 2)
        reasons.append(f"**{unmit_fvg}** unmitigated FVG(s) on LTF")
    if unmit_ob:
        conf += min(8, unmit_ob * 2)
        reasons.append(f"**{unmit_ob}** unmitigated order block(s) on LTF")
    if val_sweeps:
        conf += min(6, val_sweeps)
        reasons.append(f"**{val_sweeps}** validated CRT liquidity sweep(s)")

    if active_setup and active_setup.index >= len(df_ltf) - cfg.recent_setup_bars:
        direction = "LONG" if active_setup.direction == "long" else "SHORT"
        phase = PHASE_CONFIRMED
        verdict = f"TAKE {direction}"
        zone_type = active_setup.zone_type
        confirmation = active_setup.confirmation
        conf += 28
        reasons.append(f"LTF confirmation: {confirmation}")
        entry = active_setup.entry_price
        stop = active_setup.invalidation_price
        risk = abs(entry - stop) if stop != entry else entry * 0.005
        if direction == "LONG":
            target = entry + risk * cfg.rr_ratio
        else:
            target = entry - risk * cfg.rr_ratio
        reasons.append(f"Stop beyond structure invalidation · target **{cfg.rr_ratio}:1** R:R")
    elif direction in ("LONG", "SHORT"):
        verdict = f"WATCH {direction}"
        conf += 8
        reasons.append("HTF zone + bias aligned — await LTF CRT sweep / FVG / OB confirmation")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_CONFIRMED and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.35, (price - stop) / price * 100)
        tp_pct = max(0.5, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.35, (stop - price) / price * 100)
        tp_pct = max(0.5, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 1.0
        tp_pct = sl_pct * cfg.rr_ratio

    hold = "15–90 minutes (SMC scalp · LTF confirmation)"
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Exit if price invalidates OB/FVG or reclaims sweep extreme.",
        max_hold_exit="Scalp time stop — close if LTF thesis breaks.",
    )

    ote_lo = ote_hi = eq = None
    if zone is not None:
        ote_lo, ote_hi = zone.ote_zone()
        eq = zone.equilibrium

    return enrich_intra_live({
        "signal": direction if phase == PHASE_CONFIRMED else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "htf_bias": bias_label,
        "zone_type": zone_type,
        "confirmation": confirmation,
        "equilibrium": eq,
        "ote_low": ote_lo,
        "ote_high": ote_hi,
        "ltf": cfg.ltf,
        "setup_count": len(setups),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_ltf_data(
    ticker: str,
    market: str,
    cfg: ScalpSMCConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(
        ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_ltf_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(
                ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market,
            ),
        )
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ScalpSMCConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpSMCConfig()
    raw = fetch_ltf_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if raw.empty:
        return {"ticker": ticker, "error": f"No {cfg.ltf} data."}

    pipeline = run_smc_pipeline(raw, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)
    smc_cfg = _smc_config(cfg)
    return {
        "ticker": ticker,
        "market": market,
        "ltf": cfg.ltf,
        "htf_rule": smc_cfg.htf_rule,
        "mtf_rule": smc_cfg.mtf_rule,
        "bars_ltf": len(pipeline["df_ltf"]),
        "bars_htf": len(pipeline["df_htf"]),
        "last_close": float(pipeline["df_ltf"]["Close"].iloc[-1]),
        "bias": pipeline["bias"].value,
        "setup_count": len(pipeline.get("setups") or []),
        "fvg_count": len(pipeline.get("fvgs") or []),
        "ob_count": len(pipeline.get("order_blocks") or []),
        "signal_history": _setup_history(pipeline.get("setups") or []),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ScalpSMCConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpSMCConfig()
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
        "ltf": cfg.ltf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
